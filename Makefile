.PHONY: worker api

worker:
	poetry run taskiq worker backend.workers.broker:broker backend.workers.tasks

api:
	poetry run uvicorn backend.api.main:app --host 127.0.0.1 --port 8001 --reload