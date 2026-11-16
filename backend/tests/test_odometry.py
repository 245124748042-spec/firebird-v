import math
import unittest
from types import SimpleNamespace

from config import Settings
from odometry import (DifferentialDriveOdometry, calibration_is_valid,
                      command_pose_enabled, map_heading_to_radians)
from risk_map import RiskMap
from route_executor import CommandTracker
from serial_service import parse_telemetry


class TelemetryEncoderParsingTests(unittest.TestCase):
    def test_legacy_18_field_frame(self):
        tel = parse_telemetry("$FB,100,1,2,3,4,5,250,500,200,10,20,0,F,100,1,0,A")
        self.assertIsNotNone(tel)
        self.assertIsNone(tel.left_encoder_count)
        self.assertIsNone(tel.right_encoder_count)
        self.assertEqual(tel.movement, "F")

    def test_extended_20_field_frame_reads_both_counters(self):
        tel = parse_telemetry("$FB,100,1,2,3,4,5,250,500,200,10,20,0,F,100,1,0,A,4294967294,42")
        self.assertIsNotNone(tel)
        self.assertEqual(tel.left_encoder_count, 0xFFFFFFFE)
        self.assertEqual(tel.right_encoder_count, 42)

    def test_current_firebird_frame_accepts_fwd_and_real_sensor_fields(self):
        tel = parse_telemetry("$FB,5962,632,606,650,574,538,284,398,431,0,34,0,FWD,248,1,16,A,63,85")
        self.assertIsNotNone(tel)
        self.assertEqual((tel.left_ir, tel.center_ir, tel.right_ir, tel.side_ir, tel.ir5), (632, 606, 650, 574, 538))
        self.assertEqual((tel.temperature_tenths, tel.humidity_tenths, tel.smoke_value), (284, 398, 431))
        self.assertEqual((tel.env_risk, tel.total_risk, tel.movement), (0, 34, "F"))
        self.assertEqual((tel.left_encoder_count, tel.right_encoder_count), (63, 85))

    def test_actual_signed_firebird_frame_accepts_negative_right_encoder(self):
        tel = parse_telemetry("$FB,143746,44,591,481,524,469,273,431,418,62,100,0,RIGHT,150,1,2,A,1936,-2327")
        self.assertIsNotNone(tel)
        self.assertEqual(tel.movement, "R")
        self.assertEqual(tel.left_encoder_count, 1936)
        self.assertEqual(tel.right_encoder_count, -2327)

    def test_signed_encoder_parser_rejects_values_outside_32_bit_ranges(self):
        prefix = "$FB,143746,44,591,481,524,469,273,431,418,62,100,0,RIGHT,150,1,2,A,"
        self.assertIsNone(parse_telemetry(prefix + "-2147483649,0"))
        self.assertIsNone(parse_telemetry(prefix + "4294967296,0"))

    def test_incomplete_or_malformed_current_frame_is_ignored(self):
        self.assertIsNone(parse_telemetry("$FB,5962,632,606"))
        self.assertIsNone(parse_telemetry("$FB,5962,632,606,650,574,538,284,398,431,0,34,0,FWD,248,1,16,A,not-a-counter,85"))


class DifferentialDriveTests(unittest.TestCase):
    # Circumference is one metre, so each pulse represents one metre.
    DIAMETER = 1 / math.pi
    TRACK = 2.0
    PULSES = 1

    def make_odom(self, left=0, right=0, heading=math.pi / 2):
        odom = DifferentialDriveOdometry()
        first, initialized, project = odom.update(
            left, right, "S", wheel_diameter_m=self.DIAMETER,
            wheel_track_m=self.TRACK, pulses_per_revolution=self.PULSES,
            initial_heading_rad=heading,
        )
        self.assertTrue(initialized)
        self.assertTrue(project)
        self.assertEqual((first.x_m, first.y_m), (0.0, 0.0))
        return odom

    def update(self, odom, left, right, move):
        pose, initialized, project = odom.update(
            left, right, move, wheel_diameter_m=self.DIAMETER,
            wheel_track_m=self.TRACK, pulses_per_revolution=self.PULSES,
            initial_heading_rad=math.pi / 2,
        )
        self.assertFalse(initialized)
        self.assertTrue(project)
        return pose

    def test_first_sample_establishes_baseline_and_preserves_heading(self):
        odom = DifferentialDriveOdometry()
        pose, initialized, project = odom.update(
            500, 700, "F", wheel_diameter_m=self.DIAMETER,
            wheel_track_m=self.TRACK, pulses_per_revolution=self.PULSES,
            initial_heading_rad=0.0,
        )
        self.assertTrue(initialized)
        self.assertTrue(project)
        self.assertEqual((pose.x_m, pose.y_m, pose.heading_rad), (0.0, 0.0, 0.0))
        pose = self.update(odom, 501, 701, "F")
        self.assertAlmostEqual(pose.x_m, 1.0, places=9)
        self.assertAlmostEqual(pose.y_m, 0.0, places=9)
        self.assertEqual([map_heading_to_radians(i) for i in range(4)],
                         [math.pi / 2, 0.0, -math.pi / 2, -math.pi])

    def test_forward_and_reverse(self):
        forward = self.update(self.make_odom(), 1, 1, "F")
        reverse = self.update(self.make_odom(), 1, 1, "B")
        self.assertAlmostEqual(forward.y_m, 1.0)
        self.assertAlmostEqual(reverse.y_m, -1.0)

    def test_signed_forward_reverse_left_and_right_deltas(self):
        forward = self.update(self.make_odom(), 1, 1, "F")
        reverse = self.update(self.make_odom(), -1, -1, "B")
        left = self.update(self.make_odom(), -1, 1, "L")
        right = self.update(self.make_odom(), 1, -1, "R")
        self.assertAlmostEqual(forward.y_m, 1.0)
        self.assertAlmostEqual(reverse.y_m, -1.0)
        self.assertAlmostEqual(left.heading_rad, (math.pi / 2 + 1.0) % (2 * math.pi))
        self.assertAlmostEqual(right.heading_rad, (math.pi / 2 - 1.0) % (2 * math.pi))

    def test_signed_reverse_and_turn_are_detected_before_counts_cross_zero(self):
        reverse = self.update(self.make_odom(100, 100), 99, 99, "B")
        right = self.update(self.make_odom(100, 100), 101, 99, "R")
        self.assertAlmostEqual(reverse.y_m, -1.0)
        self.assertLess(right.heading_rad, math.pi / 2)

    def test_actual_right_turn_count_delta_turns_clockwise(self):
        odom = self.make_odom(1935, -2326)
        pose = self.update(odom, 1936, -2327, "R")
        self.assertLess(pose.heading_rad, math.pi / 2)

    def test_left_and_right_rotation(self):
        left = self.update(self.make_odom(), 1, 1, "L")
        right = self.update(self.make_odom(), 1, 1, "R")
        self.assertAlmostEqual(left.heading_rad, (math.pi / 2 + 1.0) % (2 * math.pi))
        self.assertAlmostEqual(right.heading_rad, (math.pi / 2 - 1.0) % (2 * math.pi))
        self.assertAlmostEqual(left.x_m, 0.0, places=9)
        self.assertAlmostEqual(right.y_m, 0.0, places=9)

    def test_uint32_rollover(self):
        odom = self.make_odom(0xFFFFFFFE, 0xFFFFFFFE)
        pose = self.update(odom, 1, 1, "F")
        self.assertAlmostEqual(pose.y_m, 3.0)

    def test_uint32_rollover_remains_unsigned_during_reverse(self):
        odom = self.make_odom(0xFFFFFFFE, 0xFFFFFFFE)
        pose = self.update(odom, 1, 1, "B")
        self.assertAlmostEqual(pose.y_m, -3.0)

    def test_duplicate_sample_does_not_move_or_append_a_pose(self):
        odom = self.make_odom(10, 10)
        before = odom.pose
        pose, initialized, project = odom.update(
            10, 10, "F", wheel_diameter_m=self.DIAMETER,
            wheel_track_m=self.TRACK, pulses_per_revolution=self.PULSES,
            initial_heading_rad=math.pi / 2,
        )
        self.assertFalse(initialized)
        self.assertFalse(project)
        self.assertEqual(pose, before)

    def test_counter_reset_establishes_new_baseline_without_pose_jump(self):
        odom = self.make_odom(500, 500)
        before = odom.pose
        reset_pose, initialized, project = odom.update(
            0, 0, "F", wheel_diameter_m=self.DIAMETER,
            wheel_track_m=self.TRACK, pulses_per_revolution=self.PULSES,
            initial_heading_rad=math.pi / 2,
        )
        self.assertFalse(initialized)
        self.assertFalse(project)
        self.assertEqual(reset_pose, before)
        recovered = self.update(odom, 1, 1, "F")
        self.assertAlmostEqual(recovered.y_m, before.y_m + 1.0)

    def test_signed_counter_reset_does_not_move_and_recovers(self):
        odom = self.make_odom(1000, -1000)
        before = odom.pose
        reset_pose, initialized, project = odom.update(
            0, 0, "R", wheel_diameter_m=self.DIAMETER,
            wheel_track_m=self.TRACK, pulses_per_revolution=self.PULSES,
            initial_heading_rad=math.pi / 2,
        )
        self.assertFalse(initialized)
        self.assertFalse(project)
        self.assertEqual(reset_pose, before)
        recovered = self.update(odom, 1, -1, "R")
        self.assertLess(recovered.heading_rad, before.heading_rad)

    def test_signed_int32_rollover(self):
        odom = self.make_odom(0x7FFFFFFF, 0x7FFFFFFF)
        pose = self.update(odom, -0x80000000, -0x80000000, "F")
        self.assertAlmostEqual(pose.y_m, 1.0)

    def test_missing_calibration_uses_command_pose(self):
        self.assertFalse(calibration_is_valid(None, self.TRACK, self.PULSES, 0.5))
        self.assertFalse(calibration_is_valid(self.DIAMETER, 0, self.PULSES, 0.5))
        self.assertTrue(command_pose_enabled(True, False))
        self.assertFalse(command_pose_enabled(True, True))
        risk_map = RiskMap(Settings(map_rows=5, map_columns=5))
        tracker = CommandTracker(risk_map)
        tracker.note_sent("MOVE:FORWARD", apply_pose=True)
        tracker.sent_at -= 2.0
        tracker.on_telemetry(SimpleNamespace(movement="S"),
                             apply_command_pose=command_pose_enabled(True, False))
        self.assertEqual(risk_map.pose.row, 3)

    def test_exact_arc_integration_and_straight_limit(self):
        odom = self.make_odom(heading=0.0)
        arc = self.update(odom, 0, 1, "F")
        self.assertAlmostEqual(arc.x_m, math.sin(0.5), places=9)
        self.assertAlmostEqual(arc.y_m, 1 - math.cos(0.5), places=9)

        straight = self.update(self.make_odom(heading=0.0), 1, 1, "F")
        self.assertAlmostEqual(straight.x_m, 1.0, places=9)
        self.assertAlmostEqual(straight.y_m, 0.0, places=9)


class MapOdometryTests(unittest.TestCase):
    def test_map_heading_is_preserved_and_path_keeps_continuous_coordinates(self):
        risk_map = RiskMap(Settings(map_rows=5, map_columns=5))
        risk_map.set_pose(2, 2, heading=1)  # east
        heading_rad = 0.0  # east in the odometry frame
        risk_map.set_odometry_pose(0.1, 0.1, heading_rad, 0.5, 2, 2)
        self.assertEqual((risk_map.pose.row, risk_map.pose.col, risk_map.pose.heading), (2, 2, 1))
        self.assertAlmostEqual(risk_map.odometry_path[-1]["x"], 2.7)
        self.assertAlmostEqual(risk_map.odometry_path[-1]["y"], 2.3)

    def test_continuous_odometry_heading_is_preserved_for_map_display(self):
        risk_map = RiskMap(Settings(map_rows=5, map_columns=5))
        heading_rad = math.pi / 3
        risk_map.set_odometry_pose(0.0, 0.0, heading_rad, 0.5, 2, 2)
        self.assertAlmostEqual(risk_map.snapshot_meta()["odometry_heading_rad"], heading_rad)

    def test_encoder_delta_changes_grid_pose_and_appends_actual_trail(self):
        risk_map = RiskMap(Settings(map_rows=5, map_columns=5))
        risk_map.set_pose(2, 2, heading=0)
        odom = DifferentialDriveOdometry()
        args = dict(wheel_diameter_m=1 / math.pi, wheel_track_m=2.0,
                    pulses_per_revolution=1, initial_heading_rad=map_heading_to_radians(0))
        pose, initialized, project = odom.update(0, 0, "S", **args)
        self.assertTrue(initialized and project)
        risk_map.set_odometry_pose(pose.x_m, pose.y_m, pose.heading_rad, 0.5, 2, 2)
        pose, initialized, project = odom.update(1, 1, "F", **args)
        self.assertFalse(initialized)
        self.assertTrue(project)
        risk_map.set_odometry_pose(pose.x_m, pose.y_m, pose.heading_rad, 0.5, 2, 2)
        self.assertEqual((risk_map.pose.row, risk_map.pose.col), (0, 2))
        self.assertEqual(len(risk_map.odometry_path), 2)


if __name__ == "__main__":
    unittest.main()
