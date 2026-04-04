.PHONY: worker

worker:
	poetry run taskiq worker backend.workers.broker:broker backend.workers.tasks