import socket

_original_getaddrinfo = socket.getaddrinfo

def _patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    res = _original_getaddrinfo(host, port, family, type, proto, flags)
    if host and "supabase.com" in str(host):
        res = [r for r in res if r[0] == socket.AF_INET]
    return res

socket.getaddrinfo = _patched_getaddrinfo

print(socket.getaddrinfo("aws-0-ap-southeast-1.pooler.supabase.com", 5432))
