import { Navigate } from "react-router-dom"

/**
 * Supervision routes are deprecated in favour of workspace tabs.
 * Keep redirects so old links land on the shell.
 */
export default function SupervisionLayout() {
  return <Navigate to="/" replace />
}
