# M5 Console. Run from console/.
.PHONY: test typecheck build run run-mock types
test:
	npm test
typecheck:
	npx tsc --noEmit
build:
	npm run build
run:
	npm run dev
run-mock:
	npm run dev   # with no services running every panel falls back to fixtures and shows a MOCK/offline badge
types:
	npm run gen:types
