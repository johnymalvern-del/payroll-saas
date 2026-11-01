export const strings = {
  exceptions: {
    title: 'Exceptions queue',
    typeFilterLabel: 'Type',
    typeFilterAll: 'All types',
    empty: 'No exceptions match the current filters.',
    loading: 'Loading exceptions…',
    retry: 'Retry',
    loadMore: 'Load more',
    filterClientNote:
      'Type filter applies to the items currently loaded (client-side). Server-side support pending.',
    applySuggestion: 'Apply suggestion',
    applySuggestionConfirmTitle: 'Apply suggested adjustment?',
    applySuggestionConfirmBody:
      'This will change recorded times on this exception. Continue?',
    suggestedWorked: 'Suggested: worked',
  },
  exceptionTypes: {
    missing_out: 'Missing clock-out',
    missing_in: 'Missing clock-in',
    no_shift_match: 'No shift match',
    low_confidence: 'Low confidence',
    absent_expected: 'Absent (expected)',
    overtime_unapproved: 'Unapproved overtime',
    too_long: 'Shift too long',
    duplicate: 'Duplicate punch',
    device_clock_gap: 'Device clock gap',
    employee_query: 'Employee query',
  },
  employees: {
    loadError: 'Could not load employees.',
    retry: 'Retry',
  },
  adjustment: {
    dateLabel: 'Date',
    startLabel: 'Start',
    endLabel: 'End',
    nextDayIndicator: '+1 day',
    reasonCodeLabel: 'Reason code',
    reasonCodeTooLong: 'Reason code must be 40 characters or fewer.',
  },
  resolve: {
    reasonCodeHint: 'Describe the reason for this change.',
    reasonOther: 'Other',
  },
  errors: {
    dayLocked: 'This day is locked and cannot be adjusted.',
    cannotAdjustOwn: 'You cannot adjust your own record.',
    recordChanged: 'The record changed since it was loaded. Reload and try again.',
    permissionDenied: 'You do not have permission to do this.',
    notFound: 'Not found.',
    validationFailed: 'Validation failed.',
    networkError: 'Network error. Try again.',
    unknown: 'Something went wrong.',
  },
  common: {
    retry: 'Retry',
    cancel: 'Cancel',
    confirm: 'Confirm',
    dismiss: 'Dismiss',
  },
} as const;

export type Strings = typeof strings;