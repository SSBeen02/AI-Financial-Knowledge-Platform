const AUTH_ERROR_MAP: Record<string, string> = {
  "Invalid login credentials": "이메일 또는 비밀번호가 올바르지 않습니다.",
  "User already registered": "이미 가입된 이메일입니다. 로그인해 주세요.",
  "Email not confirmed": "이메일 인증이 완료되지 않았습니다. 메일함을 확인해 주세요.",
  "Password should be at least 6 characters":
    "비밀번호는 6자 이상이어야 합니다.",
  "Unable to validate email address: invalid format":
    "올바른 이메일 형식을 입력해 주세요.",
  "Signup requires a valid password": "유효한 비밀번호를 입력해 주세요.",
  "Email rate limit exceeded":
    "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.",
  "New password should be different from the old password":
    "새 비밀번호는 기존 비밀번호와 달라야 합니다.",
  "Password is known to be weak":
    "비밀번호가 너무 단순합니다. 더 강력한 비밀번호를 사용해 주세요.",
};

export function getAuthErrorMessage(error: string): string {
  for (const [key, message] of Object.entries(AUTH_ERROR_MAP)) {
    if (error.includes(key)) {
      return message;
    }
  }

  if (error.includes("duplicate") || error.includes("already exists")) {
    return "이미 가입된 이메일입니다. 로그인해 주세요.";
  }

  return "요청 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.";
}
