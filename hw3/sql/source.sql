-- Same raw S3 object as Python MapReduce. No Python UDFs or imported MR results.
-- Explicit Unicode whitespace set matches Python str.strip(), including tabs/newlines.
CREATE TEMP MACRO strip_whitespace(value) AS trim(value,
  concat(chr(9), chr(10), chr(11), chr(12), chr(13), chr(28), chr(29), chr(30), chr(31),
         chr(32), chr(133), chr(160), chr(5760), chr(8192), chr(8193), chr(8194),
         chr(8195), chr(8196), chr(8197), chr(8198), chr(8199), chr(8200), chr(8201),
         chr(8202), chr(8232), chr(8233), chr(8239), chr(8287), chr(12288)));

CREATE TEMP TABLE source AS
SELECT source, vacancy_id, name, role, area, key_skills, salary_from, salary_to, currency, gross, experience
FROM {reader};

CREATE TEMP TABLE frontend AS
SELECT *,
  list_sort(list_distinct(list_filter(
    list_transform(string_split(coalesce(key_skills, ''), ';'), x -> lower(strip_whitespace(x))),
    x -> x <> ''
  ))) AS skills_all
FROM source
WHERE strip_whitespace(role) = 'Программист, разработчик'
  AND regexp_matches(lower(name), '(^|[^a-zа-яё])(front[ -]*end|фронт[ -]*[еэ]нд)([^a-zа-яё]|$)');

CREATE TEMP TABLE stacks AS
SELECT row_number() OVER () AS rid,
       CASE WHEN {cap} = 0 THEN skills_all ELSE list_slice(skills_all, 1, {cap}) END AS skills
FROM frontend;

CREATE TEMP TABLE expanded AS
SELECT rid, skill, pos
FROM stacks, unnest(skills) WITH ORDINALITY AS u(skill, pos);
