/** Start a live mission as soon as a valid backend route is ready. */
export async function autoStartMission(routeFound, startMission) {
  if (!routeFound) return false
  await startMission()
  return true
}
