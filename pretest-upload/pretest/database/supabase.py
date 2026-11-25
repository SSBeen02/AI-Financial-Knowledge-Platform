def create_supabase_client(url: str, key: str):
    try:
        from supabase import create_client
    except ImportError as exc:
        raise RuntimeError(
            "supabase 패키지가 없습니다. requirements.txt를 설치해 주세요."
        ) from exc
    try:
        return create_client(url, key)
    except Exception as exc:
        raise RuntimeError(
            "Supabase 클라이언트를 만들지 못했습니다. SUPABASE_URL과 service role 키를 확인해 주세요."
        ) from exc
