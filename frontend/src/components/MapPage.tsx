import Map3D from './Map3D'
import CameraPanel from './CameraPanel'
import Controls from './Controls'
import RoutePlanner from './RoutePlanner'
import CellDetails from './CellDetails'
import StatusTiles from './StatusTiles'

export default function MapPage() {
  return <div className="space-y-4">
    <StatusTiles />
    <div className="grid items-stretch gap-4 xl:grid-cols-2">
      <Map3D mode="live" />
      <Map3D mode="route" />
    </div>
    <CameraPanel />
    <div className="grid gap-4 lg:grid-cols-3">
      <Controls />
      <RoutePlanner />
      <CellDetails />
    </div>
  </div>
}
