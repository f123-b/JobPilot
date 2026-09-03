from app import db


def test_job_fingerprint_is_stable():
    a = {"title": "AI Agent Engineer", "company": "Acme", "location": "Singapore", "url": "https://example.com/job/1?utm=x"}
    b = {"title": " ai agent engineer ", "company": "ACME", "location": "Singapore", "url": "example.com/job/1"}
    assert db.job_fingerprint(a) == db.job_fingerprint(b)
