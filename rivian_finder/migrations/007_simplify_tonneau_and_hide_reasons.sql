-- Powered tonneau is now simply yes / no / unknown; "not interested" reasons are now four.
UPDATE vehicle_attributes SET value = 'yes' WHERE field = 'tonneau' AND value IN ('confirmed_operational', 'listed_unverified');
UPDATE vehicle_attributes SET value = 'no' WHERE field = 'tonneau' AND value = 'confirmed_absent';
DELETE FROM vehicle_attributes WHERE field = 'tonneau' AND id NOT IN (
    SELECT MIN(id) FROM vehicle_attributes WHERE field = 'tonneau' GROUP BY vehicle_id, listing_id, value, source, method);
UPDATE user_overrides SET value = 'yes' WHERE field = 'tonneau' AND value IN ('confirmed_operational', 'listed_unverified');
UPDATE user_overrides SET value = 'no' WHERE field = 'tonneau' AND value = 'confirmed_absent';

UPDATE vehicles SET hidden_reason = 'title_issues' WHERE hidden_reason IN ('branded_title', 'accident');
UPDATE vehicles SET hidden_reason = 'too_far' WHERE hidden_reason = 'distance';
UPDATE vehicles SET hidden_reason = 'other'
    WHERE hidden_reason IS NOT NULL AND hidden_reason NOT IN ('title_issues', 'too_far', 'sold', 'other');
