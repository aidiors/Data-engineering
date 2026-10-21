-- Units: RUB per month, declared net only. Open bounds are estimates, not offers.
CREATE TEMP TABLE salary_values AS
WITH numeric_bounds AS (
  SELECT *, try_cast(salary_from AS DOUBLE) AS lo, try_cast(salary_to AS DOUBLE) AS hi
  FROM frontend WHERE currency = 'RUR' AND gross = 'false'
)
SELECT *, CASE WHEN lo IS NOT NULL AND hi IS NOT NULL THEN (lo+hi)/2
               ELSE coalesce(lo,hi) END AS salary_value
FROM numeric_bounds
WHERE (lo IS NULL OR (isfinite(lo) AND lo > 0))
  AND (hi IS NULL OR (isfinite(hi) AND hi > 0))
  AND (salary_from IS NULL OR salary_from = '' OR lo IS NOT NULL)
  AND (salary_to IS NULL OR salary_to = '' OR hi IS NOT NULL)
  AND (lo IS NULL OR hi IS NULL OR lo <= hi)
  AND (lo IS NOT NULL OR hi IS NOT NULL);
