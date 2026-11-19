FROM node:22-slim AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY index.html ./
COPY nginx.conf ./
COPY public ./public
COPY tsconfig.json ./
COPY tsconfig.app.json ./
COPY tsconfig.node.json ./
COPY vite.config.ts ./
COPY src ./src
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
