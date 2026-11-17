"""Hardware-command safety and Pi command ordering tests (no hardware used)."""
import asyncio
import time
from types import SimpleNamespace
import unittest

from config import Settings
from main import Context, route_control
from rair_planner import plan_route
from starlette.responses import Response
from main import raspberry_pi_command_next
from schemas import Telemetry


def telemetry(**changes):
    values = dict(
        left_ir=100, center_ir=100, right_ir=100, side_ir=100, ir5=100,
        temperature_tenths=250, humidity_tenths=500, smoke_value=100,
        obstacle_detected=False, movement="S", risk_score=0, person_count=0,
        dht_ok=True, flags=0, left_encoder_count=10, right_encoder_count=10,
        source="LIVE_PI",
    )
    values.update(changes)
    return Telemetry(**values)


class NavigationSafetyTests(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        # Values below are test fixtures only. Defaults in shipped config remain
        # unset for PPR and map-cell size; no calibration is written to a file.
        settings = Settings(_env_file=None, raspberry_pi_mode=True, serial_port="", encoder_pulses_per_revolution=32,
                            map_cell_size_m=0.25)
        self.ctx = Context(settings, self.loop)
        self.ctx.pi_latest = telemetry()
        self.ctx.pi_last_rx = time.monotonic()
        self.ctx.pi_person_count = 0

    def tearDown(self):
        self.loop.close()

    def move(self, command="MOVE:FORWARD"):
        return self.ctx.send_move(command, "api")

    def test_manual_movement_is_allowed_only_through_live_safety_gate(self):
        ok, _ = self.move()
        self.assertTrue(ok)
        self.assertEqual(self.ctx.take_pi_command()["command"], "MOVE:FORWARD")

    def test_stale_telemetry_blocks_manual_movement_but_not_stop(self):
        self.ctx.pi_last_rx -= 2
        ok, reason = self.move()
        self.assertFalse(ok)
        self.assertIn("stale", reason.lower())
        stop_ok, _ = self.move("MOVE:STOP")
        self.assertTrue(stop_ok)
        self.assertEqual(self.ctx.take_pi_command()["command"], "MOVE:STOP")

    def test_pi_can_poll_queued_stop_after_telemetry_becomes_stale(self):
        self.ctx.pi_last_rx -= 4
        self.ctx.queue_pi_command("MOVE:STOP")
        self.ctx._pi_pending_command["created"] -= 5
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(ctx=self.ctx)))

        result = asyncio.run(raspberry_pi_command_next(request, Response()))

        self.assertEqual(result["command"], "MOVE:STOP")

    def test_emergency_latch_blocks_movement_but_not_stop(self):
        self.ctx.emergency_stop_latched = True
        ok, reason = self.move()
        self.assertFalse(ok)
        self.assertIn("Emergency stop", reason)
        self.assertTrue(self.move("MOVE:STOP")[0])

    def test_obstacle_and_critical_hazard_block_all_movement_but_not_stop(self):
        self.ctx.pi_latest = telemetry(obstacle_detected=True)
        self.assertFalse(self.move()[0])
        self.assertTrue(self.move("MOVE:STOP")[0])
        self.ctx.pi_latest = telemetry(risk_score=80)
        self.assertFalse(self.move("MOVE:LEFT")[0])

    def test_in_flight_movement_ack_is_rejected_after_stop_supersedes_it(self):
        queued, message = self.ctx.queue_pi_command("MOVE:FORWARD")
        self.assertTrue(queued)
        movement_id = int(message.partition(":")[2])
        self.assertEqual(self.ctx.take_pi_command()["commandId"], movement_id)

        stop_queued, stop_message = self.ctx.queue_pi_command("MOVE:STOP")
        self.assertTrue(stop_queued)
        stop_id = int(stop_message.partition(":")[2])
        self.assertFalse(self.ctx.acknowledge_pi_command(movement_id, True, None))
        self.assertEqual(self.ctx.take_pi_command()["commandId"], stop_id)
        self.assertTrue(self.ctx.acknowledge_pi_command(stop_id, True, None))

    def test_missing_calibration_blocks_manual_motion_and_reports_unavailable_odometry(self):
        self.ctx.settings.encoder_pulses_per_revolution = None
        self.ctx.settings.map_cell_size_m = None
        ok, reason = self.move()
        self.assertFalse(ok)
        self.assertIn("calibration", reason.lower())
        self.assertEqual(self.ctx.map_snapshot().odometry_status, "calibration_missing")

    def test_default_calibration_does_not_assume_encoder_count_convention_or_cell_size(self):
        settings = Settings(_env_file=None, raspberry_pi_mode=True, serial_port="")
        self.assertIsNone(settings.encoder_pulses_per_revolution)
        self.assertIsNone(settings.map_cell_size_m)

    def test_backend_start_action_starts_a_safe_planned_mission_automatically(self):
        start = (self.ctx.map.pose.row, self.ctx.map.pose.col)
        goal = (start[0] - 1, start[1])
        self.ctx.last_route = plan_route(self.ctx.map.cost_grid(), start, goal, 0, 1.5, True, 40.0)
        self.ctx.last_goal = goal
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(ctx=self.ctx)))

        result = asyncio.run(route_control("start", request))

        self.assertTrue(result["success"])
        self.assertEqual(self.ctx.executor.state, "FOLLOWING")


if __name__ == "__main__":
    unittest.main()
