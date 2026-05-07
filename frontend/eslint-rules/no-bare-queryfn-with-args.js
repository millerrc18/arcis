/**
 * ESLint rule: no-bare-queryfn-with-args
 *
 * Flags useQuery() calls where queryFn is a bare MemberExpression
 * (e.g. api.getStatus) instead of an arrow function or function expression.
 *
 * A bare MemberExpression causes TanStack Query v5 to pass QueryFunctionContext
 * as the first argument to the function, which corrupts typed API calls that
 * expect their own arguments (e.g. ?desk=[object Object] URL corruption).
 *
 * Correct:   queryFn: () => api.getStatus()
 * Flagged:   queryFn: api.getStatus
 *
 * Arrow functions (ArrowFunctionExpression) and function expressions
 * (FunctionExpression) are always accepted regardless of body.
 */

export default {
  meta: {
    type: 'problem',
    docs: {
      description:
        'useQuery queryFn must not be a bare MemberExpression; wrap in an arrow function to prevent QueryFunctionContext leakage as first arg',
    },
    schema: [],
    messages: {
      bareQueryFn:
        'useQuery queryFn is a bare reference; use () => api.foo() arrow form to prevent QueryFunctionContext leakage as first arg',
    },
  },

  create(context) {
    function isUseQueryCall(node) {
      return (
        node.type === 'CallExpression' &&
        node.callee.type === 'Identifier' &&
        node.callee.name === 'useQuery'
      )
    }

    function getQueryOptions(callNode) {
      if (callNode.arguments.length === 0) return null
      const firstArg = callNode.arguments[0]
      if (firstArg.type === 'ObjectExpression') return firstArg
      return null
    }

    return {
      CallExpression(node) {
        if (!isUseQueryCall(node)) return

        const options = getQueryOptions(node)
        if (!options) return

        for (const prop of options.properties) {
          if (
            prop.type === 'Property' &&
            prop.key.type === 'Identifier' &&
            prop.key.name === 'queryFn' &&
            prop.value.type === 'MemberExpression'
          ) {
            context.report({
              node: prop.value,
              messageId: 'bareQueryFn',
            })
          }
        }
      },
    }
  },
}
