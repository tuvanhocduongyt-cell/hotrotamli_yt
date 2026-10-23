"""Initialize new learning documents without touching any existing records."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.data_store import DataStore


def initialize(store):
    for name, default in [('learning_tasks.json', {}), ('learning_events.json', [])]:
        if store.backend == 'supabase':
            row = store.client.get_document(name)
            if row is None:
                store.client.save_document(name, default, 0)
                print('Created', name)
            else:
                print('Kept', name)
        elif not store.local_path(name).exists():
            store.save_document(name, default)
            print('Created', name)


if __name__ == '__main__':
    initialize(DataStore())
