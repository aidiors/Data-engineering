-- Table 1: denominators include all Frontend vacancies, pay only eligible net RUB.
SELECT f.area AS region, count(*) AS vacancies,
       count(s.salary_value) AS paid_rur_net, median(s.salary_value) AS median_rur_net,
       avg(len(f.skills_all)) AS mean_skills
FROM frontend f LEFT JOIN salary_values s USING (source,vacancy_id)
WHERE f.area IN (SELECT unnest(?::VARCHAR[]))
GROUP BY f.area ORDER BY vacancies DESC;

-- Table 2: one occurrence per skill per vacancy, with regional denominator.
WITH frequencies AS (
  SELECT area AS region, skill, count(*) AS vacancies
  FROM frontend, unnest(skills_all) AS u(skill)
  WHERE area IN (SELECT unnest(?::VARCHAR[]))
  GROUP BY area,skill
), totals AS (
  SELECT area AS region,count(*) AS total FROM frontend GROUP BY area
)
SELECT region,skill,vacancies,100.0*vacancies/total AS demand_pct
FROM frequencies JOIN totals USING (region)
QUALIFY row_number() OVER (PARTITION BY region ORDER BY vacancies DESC,skill) <= 15
ORDER BY region,vacancies DESC,skill;
