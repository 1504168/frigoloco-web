import { toast as sonnerToast } from 'sonner'

// Errors and warnings stay longer than the Toaster default so the user has time to read them.
const PROBLEM_TOAST_DURATION_MS = 8_000

const showErrorToast: typeof sonnerToast.error = (message, options) =>
  sonnerToast.error(message, { duration: PROBLEM_TOAST_DURATION_MS, ...options })

const showWarningToast: typeof sonnerToast.warning = (message, options) =>
  sonnerToast.warning(message, { duration: PROBLEM_TOAST_DURATION_MS, ...options })

export const toast = {
  success: sonnerToast.success,
  info: sonnerToast.info,
  warning: showWarningToast,
  error: showErrorToast,
}
