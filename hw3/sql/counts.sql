SELECT 1 AS k, list_value(skill) AS skills, count(*)::BIGINT AS frequency
FROM expanded GROUP BY skill
UNION ALL
SELECT 2, list_value(a.skill, b.skill), count(*)::BIGINT
FROM expanded a JOIN expanded b ON a.rid = b.rid AND a.pos < b.pos
GROUP BY a.skill, b.skill
UNION ALL
SELECT 3, list_value(a.skill, b.skill, c.skill), count(*)::BIGINT
FROM expanded a
JOIN expanded b ON a.rid = b.rid AND a.pos < b.pos
JOIN expanded c ON a.rid = c.rid AND b.pos < c.pos
GROUP BY a.skill, b.skill, c.skill
ORDER BY k, skills;
