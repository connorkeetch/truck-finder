-- v4: one photo per truck (provider image URL + local thumbnail cache).
ALTER TABLE listings ADD COLUMN photo_url TEXT;           -- first/primary photo the provider or page offers
ALTER TABLE listings ADD COLUMN photo_count INTEGER;
ALTER TABLE vehicles ADD COLUMN photo_url TEXT;           -- user-chosen photo (URL or 'upload'); beats listing photos
ALTER TABLE vehicles ADD COLUMN photo_cached_from TEXT;   -- source of the local thumbnail in data/photos/
ALTER TABLE capture_queue ADD COLUMN image_url TEXT;      -- page preview image sent by the browser extension

UPDATE listings SET photo_url = json_extract(raw_json, '$.retailListing.primaryImage'),
                    photo_count = json_extract(raw_json, '$.retailListing.photoCount')
 WHERE source_key = 'autodev' AND raw_json IS NOT NULL AND json_valid(raw_json);
