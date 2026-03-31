FROM node:22-alpine AS build

WORKDIR /app
COPY package.json svelte.config.js tsconfig.json vite.config.ts /app/
COPY src /app/src

RUN npm install && npm run build

FROM node:22-alpine

WORKDIR /app
COPY --from=build /app/package.json /app/package.json
COPY --from=build /app/build /app/build
COPY --from=build /app/node_modules /app/node_modules

ENV HOST=0.0.0.0
ENV PORT=3000

CMD ["node", "build"]

