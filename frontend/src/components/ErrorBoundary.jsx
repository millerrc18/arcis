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
          <h2 className="text-lg font-medium mb-2" style={{ color: 'var(--arcis-danger)' }}>Something went wrong</h2>
          <p className="text-sm mb-4" style={{ color: 'var(--arcis-text-secondary)' }}>
            {this.state.error?.message || 'An unexpected error occurred'}
          </p>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            className="px-4 py-2 text-white rounded text-sm transition-colors"
            style={{ background: 'var(--arcis-accent)' }}
            onMouseEnter={(e) => e.target.style.background = 'var(--arcis-accent-hover)'}
            onMouseLeave={(e) => e.target.style.background = 'var(--arcis-accent)'}
          >
            Try Again
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
