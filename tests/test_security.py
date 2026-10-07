from keyholder.security import generate_token, hash_token, valid_token, verify_token


def test_token_entropy_and_validation() -> None:
    tokens = {generate_token() for _ in range(1000)}
    assert len(tokens) == 1000
    assert all(valid_token(t) and len(t) == 43 for t in tokens)
    token = generate_token()
    digest = hash_token(token)
    assert token != digest and len(digest) == 64
    assert verify_token(token, digest)
    assert not verify_token(generate_token(), digest)
    for bad in ["", "a" * 42, "a" * 44, "ü" * 43, "/" * 43]:
        assert not valid_token(bad)
        assert not verify_token(bad, digest)
