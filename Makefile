APPDIR=src/

.PHONY: deploy
deploy:
	sls deploy

.PHONY: format
format:
	@for app in $(shell ls ${APPDIR}); \
		do echo "black ${APPDIR}$${app}..." && \
		black "${APPDIR}$${app}"; \
	done

.PHONY: flake8
flake8:
	@rm -Rf pyflakes.log
	@for app in $(shell ls ${APPDIR}); \
		do echo "flake8 ${APPDIR}$${app}/*.py" && \
		flake8 ${APPDIR}$${app}/*.py >> pyflakes.log; \
	done

.PHONY: lint
lint: format flake8