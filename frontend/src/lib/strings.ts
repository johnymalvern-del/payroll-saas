export const strings = {
  appName: "Payroll",
  genericError: "Something went wrong. Please try again.",
  login: {
    title: "Sign in",
    identifierLabel: "Username or email",
    passwordLabel: "Password",
    tenantLabel: "Tenant slug (development only)",
    submit: "Sign in",
    error: "Sign-in failed. Check your details.",
  },
  changePassword: {
    title: "Change your password",
    intro: "You must set a new password before you can continue.",
    currentLabel: "Current password",
    newLabel: "New password",
    confirmLabel: "Confirm new password",
    submit: "Change password",
    tooShort: "Password must be at least 8 characters.",
    mismatch: "Passwords do not match.",
  },
  shell: {
    logout: "Sign out",
  },
  home: {
    welcome: "Signed in.",
    nextPhase:
      "Role-based navigation and dashboard cards arrive in the next phase.",
  },
} as const;
