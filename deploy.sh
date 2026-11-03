#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="netflix-household-1027"
REGION="asia-northeast3"
SERVICE="netflix-household"
TOPIC_ID="gmail-netflix"
SUBSCRIPTION="gmail-netflix-push"
SECRET="gmail-token"
INVOKER="netflix-invoker"
SCHEDULER_JOB="gmail-watch-renew"

FROM_STEP="${1:-1}"

cd "$(dirname "$0")"

PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
COMPUTE_SERVICE_ACCOUNT="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
INVOKER_SERVICE_ACCOUNT="${INVOKER}@${PROJECT_ID}.iam.gserviceaccount.com"

retry() {
  local attempts="$1" delay="$2" description="$3"
  shift 3
  for attempt in $(seq 1 "$attempts"); do
    if "$@"; then
      return 0
    fi
    if [ "$attempt" -eq "$attempts" ]; then
      echo "${description}에 ${attempts}번 실패했습니다." >&2
      return 1
    fi
    echo "${description} 실패, IAM 전파를 기다렸다가 다시 시도합니다 (${attempt}/${attempts})"
    sleep "$delay"
  done
}

service_url() {
  gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT_ID" \
    --format='value(status.url)'
}

step_1() {
  echo "==> 1. API 활성화"
  gcloud services enable \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    pubsub.googleapis.com \
    cloudscheduler.googleapis.com \
    secretmanager.googleapis.com \
    gmail.googleapis.com \
    iam.googleapis.com \
    --project "$PROJECT_ID"
}

step_2() {
  echo "==> 2. Secret ${SECRET} 생성"
  gcloud secrets create "$SECRET" \
    --data-file=token.json \
    --replication-policy=automatic \
    --project "$PROJECT_ID"
}

step_3() {
  echo "==> 3. 기본 compute 서비스 계정에 빌드 권한과 Secret 읽기 권한 부여"
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${COMPUTE_SERVICE_ACCOUNT}" \
    --role=roles/run.builder \
    --condition=None \
    --quiet > /dev/null
  gcloud secrets add-iam-policy-binding "$SECRET" \
    --member="serviceAccount:${COMPUTE_SERVICE_ACCOUNT}" \
    --role=roles/secretmanager.secretAccessor \
    --project "$PROJECT_ID" > /dev/null
}

deploy_service() {
  gcloud run deploy "$SERVICE" \
    --source . \
    --region "$REGION" \
    --no-allow-unauthenticated \
    --memory 2Gi \
    --cpu 1 \
    --concurrency 1 \
    --max-instances 1 \
    --timeout 120 \
    --set-env-vars "PROJECT_ID=${PROJECT_ID},TOPIC_ID=${TOPIC_ID}" \
    --set-secrets "GMAIL_TOKEN=${SECRET}:latest" \
    --project "$PROJECT_ID" \
    --quiet
}

step_4() {
  echo "==> 4. Cloud Run 배포"
  retry 3 30 "Cloud Run 배포" deploy_service
  echo "서비스 주소: $(service_url)"
}

grant_invoker() {
  gcloud run services add-iam-policy-binding "$SERVICE" \
    --region "$REGION" \
    --member="serviceAccount:${INVOKER_SERVICE_ACCOUNT}" \
    --role=roles/run.invoker \
    --project "$PROJECT_ID" > /dev/null
}

step_5() {
  echo "==> 5. 호출용 서비스 계정 ${INVOKER} 생성과 run.invoker 부여"
  gcloud iam service-accounts create "$INVOKER" \
    --display-name="Netflix household invoker" \
    --project "$PROJECT_ID"
  retry 6 10 "run.invoker 부여" grant_invoker
}

step_6() {
  echo "==> 6. Pub/Sub 토픽 ${TOPIC_ID} 생성과 Gmail 게시 권한 부여"
  gcloud pubsub topics create "$TOPIC_ID" --project "$PROJECT_ID"
  gcloud pubsub topics add-iam-policy-binding "$TOPIC_ID" \
    --member="serviceAccount:gmail-api-push@system.gserviceaccount.com" \
    --role=roles/pubsub.publisher \
    --project "$PROJECT_ID" > /dev/null
}

step_7() {
  echo "==> 7. push 구독 ${SUBSCRIPTION} 생성"
  local url
  url="$(service_url)"
  gcloud pubsub subscriptions create "$SUBSCRIPTION" \
    --topic "$TOPIC_ID" \
    --push-endpoint="${url}/pubsub" \
    --push-auth-service-account="$INVOKER_SERVICE_ACCOUNT" \
    --push-auth-token-audience="$url" \
    --ack-deadline 120 \
    --message-retention-duration=10m \
    --project "$PROJECT_ID"
}

step_8() {
  echo "==> 8. Scheduler 작업 ${SCHEDULER_JOB} 생성"
  local url
  url="$(service_url)"
  gcloud scheduler jobs create http "$SCHEDULER_JOB" \
    --location "$REGION" \
    --schedule="0 6 * * *" \
    --time-zone="Asia/Seoul" \
    --uri="${url}/renew" \
    --http-method=POST \
    --oidc-service-account-email="$INVOKER_SERVICE_ACCOUNT" \
    --oidc-token-audience="$url" \
    --project "$PROJECT_ID"
}

step_9() {
  echo "==> 9. 첫 watch 등록"
  gcloud scheduler jobs run "$SCHEDULER_JOB" --location "$REGION" --project "$PROJECT_ID"
}

for step in 1 2 3 4 5 6 7 8 9; do
  if [ "$step" -ge "$FROM_STEP" ]; then
    echo
    "step_${step}"
  fi
done

echo
echo "==> 완료"
echo "Cloud Run 로그에서 'watch 갱신 완료'를 확인한 뒤 token.json, credentials.json 로컬 사본을 지웁니다."
