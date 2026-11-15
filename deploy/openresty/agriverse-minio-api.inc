# Include inside the wisdom-dev.local TLS server. Keep /minio/ as the console.
# S3_PUBLIC_ENDPOINT_URL=https://wisdom-dev.local (no added path prefix).
# Preserve the signed bucket/object path and Host; never strip /agriverse/.
location = /agriverse {
    proxy_pass http://minio:9000;
    proxy_http_version 1.1;
    proxy_set_header Host $http_host;
    proxy_set_header Connection "";
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_buffering off;
    proxy_request_buffering off;
    client_max_body_size 10m;
}

location ^~ /agriverse/ {
    proxy_pass http://minio:9000;
    proxy_http_version 1.1;
    proxy_set_header Host $http_host;
    proxy_set_header Connection "";
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_buffering off;
    proxy_request_buffering off;
    client_max_body_size 10m;
}
