# FrigoLoco frontend - Vite/React build served as static files by nginx.
# Build context is the frontend/ directory (Railway: Root Directory = frontend/).

# ---- Stage 1: build the static bundle -------------------------------------
FROM node:22-alpine AS build

WORKDIR /app

# Install deps first for layer caching (package files change less than source).
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# VITE_API_BASE_URL is baked in AT BUILD TIME (Vite inlines import.meta.env),
# so it must point at the deployed backend URL before `vite build` runs.
# Railway exposes service variables to the build as ARGs.
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN npm run build

# ---- Stage 2: serve dist/ with nginx --------------------------------------
FROM nginx:alpine

# The official image runs envsubst over /etc/nginx/templates/*.template at
# startup, substituting only real env vars (so ${PORT} is replaced while
# nginx's own $uri is left intact) and writing the result to conf.d/.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

# Railway injects $PORT; default to 8080 for local `docker run`.
ENV PORT=8080
EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
