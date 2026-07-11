/** RFC 7807 problem details, as returned by the crate API on errors. */
export interface ProblemDetail {
  title: string;
  status: number;
  detail?: string;
  type?: string;
  error_code?: string;
}

interface ApiErrorOptions {
  problem?: ProblemDetail;
  isNetworkError?: boolean;
}

export class ApiError extends Error {
  readonly status: number;
  readonly problem?: ProblemDetail;
  readonly isNetworkError: boolean;

  constructor(message: string, status: number, options?: ApiErrorOptions) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.problem = options?.problem;
    this.isNetworkError = options?.isNetworkError ?? false;
  }
}
