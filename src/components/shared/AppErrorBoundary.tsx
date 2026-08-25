import { Component, type ErrorInfo, type ReactNode } from "react"

type Props = { children: ReactNode }
type State = { error: Error | null }

export class AppErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("MinePulse render error", error, info.componentStack)
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex h-screen flex-col items-center justify-center gap-3 bg-background px-6 text-center">
          <p className="text-sm font-semibold text-foreground">Erreur d&apos;affichage</p>
          <p className="max-w-md text-xs text-muted">{this.state.error.message}</p>
          <button
            type="button"
            className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white"
            onClick={() => window.location.reload()}
          >
            Recharger
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
