FROM node:24-alpine

RUN apk add --no-cache nginx git python3 make g++

VOLUME [ "/OJ_FE", "/var/log/nginx/", "/data/avatar"]
EXPOSE 80

CMD ["/bin/sh", "/OJ_FE/deploy/run.sh"]
