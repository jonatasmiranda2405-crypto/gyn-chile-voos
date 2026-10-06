# Painel GYN → Chile

Site estático (GitHub Pages) com os preços de Goiânia (GYN) e, como referência, de Brasília (BSB) para Santiago (SCL) em 11/12/2026, saída a partir das 19:30, só ida, conexões aceitas.

Uma rotina do GitHub Actions busca os preços no Google Flights pela SerpApi, grava site/data.json e republica o site.

## Configurar (uma vez)

1. Crie uma conta em https://serpapi.com e copie a chave da API (o plano gratuito tem 250 buscas por mês).
2. No repositório: Settings > Secrets and variables > Actions > New repository secret. Nome SERPAPI_KEY, valor a chave.
3. Settings > Pages > Source: GitHub Actions.
4. Actions > "Atualizar preços e publicar" > Run workflow.

## Frequência

O workflow roda a cada 6 horas (2 buscas por execução, cerca de 240 por mês, dentro do plano gratuito). Para rodar de hora em hora, troque o cron para "17 * * * *" e use um plano pago da SerpApi.

## Mudar data ou horário

Edite FLIGHT_DATE e AFTER no passo "Buscar preços" do workflow.

## Limites

- O botão "Google Flights" abre a busca da rota, não a oferta exata. A compra é feita no site da companhia.
- Preços mudam em minutos. Confirme o valor final, com bagagem, no site antes de comprar.
