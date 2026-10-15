ARG OPENSEARCH_VERSION=2.19.2
FROM opensearchproject/opensearch:${OPENSEARCH_VERSION}

ARG OPENSEARCH_VERSION=2.19.2
ARG IK_PLUGIN_URL=https://release.infinilabs.com/analysis-ik/stable/opensearch-analysis-ik-${OPENSEARCH_VERSION}.zip

RUN /usr/share/opensearch/bin/opensearch-plugin install --batch "${IK_PLUGIN_URL}"

COPY --chown=opensearch:opensearch analysis/ /usr/share/opensearch/config/analysis/
