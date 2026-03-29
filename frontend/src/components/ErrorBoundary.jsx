import { Component } from 'react'

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="p-8 text-center">
          <h2 className="text-lg font-medium mb-2" style={{ color: 'var(--danger)' }}>Something went wrong</h2>
          <p className="text-sm mb-4" style={{ color: 'var(--slate-400)' }}>
            {this.state.error?.message || 'An unexpected error occurred'}
          </p>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            className="px-4 py-2 text-white rounded text-sm transition-colors"
            style={{ background: 'var(--teal-500)' }}
            onMouseEnter={(e) => e.target.style.background = 'var(--teal-600)'}
            onMouseLeave={(e) => e.target.style.background = 'var(--teal-500)'}
          >
            Try Again
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
