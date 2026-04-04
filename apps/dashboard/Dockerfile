FROM node:22-alpine AS build

WORKDIR /app
COPY apps/dashboard/package.json /app/package.json
COPY apps/dashboard/svelte.config.js /app/svelte.config.js
COPY apps/dashboard/tsconfig.json /app/tsconfig.json
COPY apps/dashboard/vite.config.ts /app/vite.config.ts
COPY apps/dashboard/src /app/src
COPY install-node.sh /app/static/install-node.sh

RUN npm install && npm run build

FROM node:22-alpine

WORKDIR /app
COPY --from=build /app/package.json /app/package.json
COPY --from=build /app/build /app/build
COPY --from=build /app/node_modules /app/node_modules

ENV HOST=0.0.0.0
ENV PORT=3000

CMD ["node", "build"]

