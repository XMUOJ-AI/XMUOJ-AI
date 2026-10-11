import axios from 'axios'

// Each HTML entry supplies its own UI services before mounting its router.
const ui = {
  $http: axios,
  $error: () => {},
  $success: () => {},
  $info: () => {},
  $warning: () => {},
  $Loading: { start () {}, finish () {}, error () {} }
}
export function setUI (services) { Object.assign(ui, services) }
export default ui
