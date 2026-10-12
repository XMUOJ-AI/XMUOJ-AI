"""Enforce immutable historical facts even for accidental ORM bulk writes."""
from django.db import migrations


CREATE = """
CREATE FUNCTION knowledge_guard_history() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' OR TG_TABLE_NAME = 'knowledge_review_event' THEN
        RAISE EXCEPTION 'knowledge history is append-only' USING ERRCODE = '23514';
    END IF;
    IF TG_TABLE_NAME = 'knowledge_dependency_change_request' THEN
        IF (to_jsonb(NEW) - ARRAY['target_dependency_id', 'status', 'review_reason', 'reviewed_by_id', 'updated_time'])
           IS DISTINCT FROM
           (to_jsonb(OLD) - ARRAY['target_dependency_id', 'status', 'review_reason', 'reviewed_by_id', 'updated_time']) THEN
            RAISE EXCEPTION 'dependency proposal and original identity are immutable' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'knowledge_mapping_batch' THEN
        IF (to_jsonb(NEW) - ARRAY['approved_version', 'status', 'reason', 'reviewed_by_id', 'updated_time'])
           IS DISTINCT FROM
           (to_jsonb(OLD) - ARRAY['approved_version', 'status', 'reason', 'reviewed_by_id', 'updated_time']) THEN
            RAISE EXCEPTION 'mapping candidates and submission versions are immutable' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER knowledge_event_immutable BEFORE UPDATE OR DELETE ON knowledge_review_event
    FOR EACH ROW EXECUTE FUNCTION knowledge_guard_history();
CREATE TRIGGER knowledge_dependency_history_immutable BEFORE UPDATE OR DELETE ON knowledge_dependency_change_request
    FOR EACH ROW EXECUTE FUNCTION knowledge_guard_history();
CREATE TRIGGER knowledge_mapping_history_immutable BEFORE UPDATE OR DELETE ON knowledge_mapping_batch
    FOR EACH ROW EXECUTE FUNCTION knowledge_guard_history();
"""

DROP = """
DROP TRIGGER knowledge_mapping_history_immutable ON knowledge_mapping_batch;
DROP TRIGGER knowledge_dependency_history_immutable ON knowledge_dependency_change_request;
DROP TRIGGER knowledge_event_immutable ON knowledge_review_event;
DROP FUNCTION knowledge_guard_history();
"""


def install(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(CREATE)


def uninstall(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DROP)


class Migration(migrations.Migration):
    dependencies = [("knowledge", "0001_initial")]
    operations = [migrations.RunPython(install, uninstall)]
