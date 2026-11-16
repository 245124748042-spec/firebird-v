import unittest

import numpy as np

from config import Settings
from rair_planner import astar, plan_route
from risk_map import CostGrid, RiskMap


def grid(rows=5, cols=5):
    return CostGrid(rows, cols, np.zeros((rows, cols), dtype=bool),
                    np.zeros((rows, cols), dtype=float), np.zeros((rows, cols), dtype=float))


class AStarRiskTests(unittest.TestCase):
    def test_avoids_blocked_cells(self):
        g = grid()
        g.blocked[2, 1:4] = True
        found, path, _ = astar(g, (2, 0), (2, 4), 1.5, 40)
        self.assertTrue(found)
        self.assertTrue(all(not g.blocked[r, c] for r, c in path))

    def test_high_risk_detour_reduces_route_risk(self):
        g = grid()
        g.risk01[2, 1:4] = 0.9
        _, shortest, _ = astar(g, (2, 0), (2, 4), None, 40)
        _, safe, _ = astar(g, (2, 0), (2, 4), 3.0, 40)
        self.assertLess(sum(g.risk01[r, c] for r, c in safe[1:]),
                        sum(g.risk01[r, c] for r, c in shortest[1:]))

    def test_no_route_when_goal_is_blocked_or_sealed(self):
        g = grid(3, 3)
        g.blocked[0, 1] = g.blocked[1, 0] = True
        self.assertEqual(astar(g, (0, 0), (2, 2), 1.5, 40)[:2], (False, []))
        g.blocked[2, 2] = True
        self.assertFalse(astar(g, (0, 0), (2, 2), 1.5, 40)[0])

    def test_risk_map_combines_measured_environment_and_marks_ir_obstacle(self):
        m = RiskMap(Settings(map_rows=5, map_columns=5))
        m.mark_sensor(2, 2, temp_c=30, smoke_raw=150, reported_risk=34)
        m.set_sensor_obstacle(1, 1, True)
        cost = m.cost_grid()
        self.assertTrue(cost.blocked[1, 1])
        self.assertAlmostEqual(cost.risk_score[2, 2], 34)
        self.assertAlmostEqual(cost.risk01[2, 2], 0.34)
        m.set_sensor_obstacle(1, 1, False)
        self.assertFalse(m.cost_grid().blocked[1, 1])

    def test_plan_returns_no_route_for_sealed_goal(self):
        g = grid(3, 3)
        g.blocked[0, 1] = g.blocked[1, 0] = True
        route = plan_route(g, (0, 0), (2, 2), 0, 1.5, True, 40)
        self.assertFalse(route.found)
        self.assertEqual(route.cells, [])


if __name__ == "__main__":
    unittest.main()
