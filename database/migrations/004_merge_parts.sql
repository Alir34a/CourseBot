-- 004: retire parts from UX — merge into episodes.
-- 1) Episode without media adopts its first media part (if any).
UPDATE episodes SET
  cover_kind = (SELECT p.kind FROM episode_parts p
                WHERE p.episode_id = episodes.id AND p.file_id IS NOT NULL AND p.file_id != ''
                ORDER BY p.part_no LIMIT 1),
  cover_file_id = (SELECT p.file_id FROM episode_parts p
                WHERE p.episode_id = episodes.id AND p.file_id IS NOT NULL AND p.file_id != ''
                ORDER BY p.part_no LIMIT 1)
WHERE (cover_file_id IS NULL OR cover_file_id = '')
  AND EXISTS (SELECT 1 FROM episode_parts p
              WHERE p.episode_id = episodes.id AND p.file_id IS NOT NULL AND p.file_id != '');
-- 2) Text parts are appended to the episode caption, in part order.
UPDATE episodes SET caption = CASE
  WHEN caption IS NULL OR caption = '' THEN COALESCE(
    (SELECT GROUP_CONCAT(t, CHAR(10) || CHAR(10)) FROM
      (SELECT p.text AS t FROM episode_parts p
       WHERE p.episode_id = episodes.id AND p.text IS NOT NULL AND p.text != ''
       ORDER BY p.part_no)), '')
  ELSE caption || CHAR(10) || CHAR(10) || COALESCE(
    (SELECT GROUP_CONCAT(t, CHAR(10) || CHAR(10)) FROM
      (SELECT p.text AS t FROM episode_parts p
       WHERE p.episode_id = episodes.id AND p.text IS NOT NULL AND p.text != ''
       ORDER BY p.part_no)), '')
  END
WHERE EXISTS (SELECT 1 FROM episode_parts p
              WHERE p.episode_id = episodes.id AND p.text IS NOT NULL AND p.text != '');
-- NOTE: episode_parts / user_part_progress tables are intentionally KEPT
-- (history + library reuse); the bot simply stops using them.
