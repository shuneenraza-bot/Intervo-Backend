-- Intervo demo queries (pgAdmin: select "intervo" → Tools → Query Tool → select one query → F5)

-- 1. All users (newest first)
SELECT id, role, name, email, created_at FROM users ORDER BY created_at DESC;

-- 2. Jobs posted by employers
SELECT j.title, u.name AS employer, j.location, j.status, j.created_at
FROM jobs j LEFT JOIN users u ON u.id = j.employer_id
ORDER BY j.created_at DESC;

-- 3. Who applied to which job
SELECT c.name AS candidate, j.title AS job, a.consent, a.status, a.created_at
FROM applications a
JOIN users c ON c.id = a.candidate_id
JOIN jobs j ON j.id = a.job_id
ORDER BY a.created_at DESC;

-- 4. Required skills and weights per job
SELECT j.title, s.name AS skill, js.weight
FROM job_skills js
JOIN jobs j ON j.id = js.job_id
JOIN skills s ON s.id = js.skill_id
ORDER BY j.title, js.weight DESC;

-- 5. Passwords are hashed (argon2), never plain text
SELECT email, LEFT(password_hash, 30) AS password_hash FROM users;

-- 6. Row count of every table
SELECT 'users' AS table_name, count(*) FROM users
UNION ALL SELECT 'jobs', count(*) FROM jobs
UNION ALL SELECT 'applications', count(*) FROM applications
UNION ALL SELECT 'job_skills', count(*) FROM job_skills
UNION ALL SELECT 'candidate_profiles', count(*) FROM candidate_profiles
UNION ALL SELECT 'interview_sessions', count(*) FROM interview_sessions
UNION ALL SELECT 'session_answers', count(*) FROM session_answers
UNION ALL SELECT 'skills', count(*) FROM skills;
