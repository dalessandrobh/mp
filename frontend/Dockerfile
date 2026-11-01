# Build do bundle. O resultado é estático — não há Node em produção.
FROM node:20-alpine AS build
WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY . .

# Valores PÚBLICOS (a anon key do Supabase é feita para ir ao navegador). Entram no bundle
# no build: mudar exige rebuild da imagem, não só reiniciar o container.
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_ANON_KEY
ENV VITE_SUPABASE_URL=$VITE_SUPABASE_URL VITE_SUPABASE_ANON_KEY=$VITE_SUPABASE_ANON_KEY

RUN npm run build

# Servidor estático. Só serve arquivos; quem separa / de /api é o Traefik.
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
