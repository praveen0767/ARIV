FROM node:20-alpine AS builder
WORKDIR /app
# Build-time arg so NEXT_PUBLIC_DEMO_MODE is baked into the bundle
ARG NEXT_PUBLIC_DEMO_MODE=true
ENV NEXT_PUBLIC_DEMO_MODE=$NEXT_PUBLIC_DEMO_MODE
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:20-alpine
WORKDIR /app
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/node_modules ./node_modules
# Expose port for Next.js
EXPOSE 3000
CMD ["npm", "run", "start"]
