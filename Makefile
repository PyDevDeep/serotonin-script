.PHONY: worker api scheduler all index-kb

worker:
	poetry run taskiq worker backend.workers.broker:broker backend.workers.tasks

scheduler:
	poetry run taskiq scheduler backend.workers.broker:scheduler backend.workers.tasks

api:
	poetry run uvicorn backend.api.main:app --host 127.0.0.1 --port 8001 --reload

index-kb:
	PYTHONPATH=. poetry run python scripts/index_knowledge_base.py

all:
	make -j 3 api worker scheduler