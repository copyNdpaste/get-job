#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$project_root"

run_with_timeout() {
  timeout_seconds=$1
  shift

  if command -v timeout >/dev/null 2>&1; then
    timeout --kill-after=5 "$timeout_seconds" "$@"
    return
  fi
  if command -v gtimeout >/dev/null 2>&1; then
    gtimeout --kill-after=5 "$timeout_seconds" "$@"
    return
  fi
  if command -v perl >/dev/null 2>&1; then
    # Keep the watchdog separate: Go clients can ignore an inherited SIGALRM.
    perl -e '
      my $seconds = shift @ARGV;
      my $pid = fork();
      die "fork failed" unless defined $pid;
      if (!$pid) { setpgrp(0, 0); exec @ARGV; exit 127; }
      $SIG{ALRM} = sub {
        kill "TERM", -$pid;
        sleep 1;
        kill "KILL", -$pid;
        waitpid($pid, 0);
        exit 124;
      };
      alarm $seconds;
      waitpid($pid, 0);
      alarm 0;
      exit(($? & 127) ? 128 + ($? & 127) : $? >> 8);
    ' "$timeout_seconds" "$@"
    return
  fi
  echo "제한 시간을 적용할 timeout 또는 perl 명령을 찾지 못했습니다." >&2
  return 127
}

mode=start
open_browser=true
repair_docker=false
for argument in "$@"; do
  case "$argument" in
    --no-open) open_browser=false ;;
    --repair-docker) repair_docker=true ;;
    restart)
      mode=restart
      open_browser=false
      ;;
    *)
      echo "사용법: ./run.sh [restart] [--no-open] [--repair-docker]" >&2
      exit 2
      ;;
  esac
done

app_url=http://localhost:41739
open_app() {
  if [ "$open_browser" != true ] || ! command -v open >/dev/null 2>&1; then
    return
  fi
  if [ -d "/Applications/Microsoft Edge.app" ]; then
    open -a "Microsoft Edge" "$app_url"
  else
    open "$app_url"
  fi
}

if [ "$mode" = restart ]; then
  echo "get-job을 빠르게 재시작합니다."
else
  echo "get-job 실행을 시작합니다."
fi
echo "- 접속 주소: $app_url"
if [ "$mode" = restart ]; then
  echo "- 이미지 재빌드와 DB 백업: 건너뜀"
elif [ "$open_browser" = true ]; then
  echo "- 준비가 끝나면 브라우저가 자동으로 열립니다."
else
  echo "- 브라우저 자동 열기: 사용 안 함 (--no-open)"
fi
echo ""

read_env_value() {
  key=$1
  if [ ! -f .env ]; then
    return
  fi
  sed -n "s/^${key}=//p" .env | tail -n 1
}

safe_volume_name() {
  case "$1" in
    "" | *[!A-Za-z0-9_.-]*) return 1 ;;
    *) return 0 ;;
  esac
}

safe_database_name() {
  case "$1" in
    "" | *[!A-Za-z0-9_]*) return 1 ;;
    *) return 0 ;;
  esac
}

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker를 찾지 못했습니다. OrbStack 또는 Docker Desktop을 먼저 설치해 주세요." >&2
  exit 1
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "로컬 설정 파일(.env)을 만들었습니다."
fi

docker_ready() {
  if docker_probe=$(run_with_timeout 5 docker version --format '{{.Server.Version}}' 2>&1); then
    return 0
  fi
  case "$docker_probe" in
    *"permission denied"* | *"operation not permitted"*)
      echo "Docker 소켓 접근 권한이 없습니다. 터미널 또는 실행 도구의 Docker 접근 권한을 확인해 주세요." >&2
      exit 1
      ;;
  esac
  return 1
}

if ! docker_ready; then
  engine_context=$(run_with_timeout 5 docker context show 2>/dev/null || true)
  if [ -n "${DOCKER_HOST:-}" ]; then
    echo "DOCKER_HOST로 지정한 Docker 엔진에 연결할 수 없습니다. 해당 주소와 엔진 상태를 확인해 주세요." >&2
    exit 1
  fi
  echo "Docker 엔진을 시작합니다…"
  if [ "$engine_context" = orbstack ] && command -v orbctl >/dev/null 2>&1; then
    if [ "$repair_docker" = true ]; then
      echo "OrbStack Docker 엔진을 재시작합니다. 다른 컨테이너도 잠시 중단될 수 있습니다."
      if ! run_with_timeout 60 orbctl restart docker; then
        echo "OrbStack Docker 재시작 요청이 완료되지 않았습니다. 엔진 응답을 확인합니다…" >&2
      fi
    elif ! run_with_timeout 30 orbctl start; then
      echo "OrbStack 시작 요청이 완료되지 않았습니다. 엔진 응답을 확인합니다…" >&2
    fi
  elif [ "$engine_context" = default ] && [ -d /Applications/OrbStack.app ]; then
    open -gja OrbStack
  elif { [ "$engine_context" = desktop-linux ] || [ "$engine_context" = default ]; } \
    && [ -d /Applications/Docker.app ]; then
    open -gja Docker
  else
    echo "선택된 Docker context의 엔진에 연결할 수 없습니다. 'docker context ls'로 연결 설정을 확인해 주세요." >&2
    exit 1
  fi
  attempt=0
  while ! docker_ready; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 18 ]; then
      echo "Docker 엔진이 응답하지 않습니다. 앱이 실행 중이어도 엔진이 멈췄을 수 있습니다." >&2
      if [ "$engine_context" = orbstack ]; then
        echo "복구 명령: ./run.sh --repair-docker (같은 엔진의 다른 컨테이너도 잠시 중단됩니다)" >&2
      fi
      exit 1
    fi
    if [ $((attempt % 3)) -eq 0 ]; then
      echo "Docker 서버 응답을 기다리고 있습니다…"
    fi
    sleep 2
  done
fi

if [ "$mode" = start ]; then
  all_services_running=true
  for service in db backend scheduler frontend; do
    if [ -z "$(docker compose ps -q "$service" 2>/dev/null)" ]; then
      all_services_running=false
      break
    fi
  done
  if [ "$all_services_running" = true ] \
    && curl -fsS --max-time 5 http://127.0.0.1:8000/health >/dev/null 2>&1 \
    && curl -fsS --max-time 5 "$app_url" >/dev/null 2>&1; then
    echo "get-job이 이미 정상 실행 중입니다."
    echo "- 화면: $app_url"
    open_app
    exit 0
  fi
fi

run_lock_dir="$project_root/data/run.local.lock"
mkdir -p "$project_root/data"
if ! mkdir "$run_lock_dir" 2>/dev/null; then
  existing_run_pid=""
  if [ -f "$run_lock_dir/pid" ]; then
    existing_run_pid=$(sed -n '1p' "$run_lock_dir/pid")
  fi
  case "$existing_run_pid" in
    *[!0-9]* | "") existing_run_pid="" ;;
  esac
  if [ -n "$existing_run_pid" ] && kill -0 "$existing_run_pid" 2>/dev/null; then
    echo "다른 get-job 실행 작업이 진행 중입니다 (PID: $existing_run_pid). 완료 후 다시 시도해 주세요." >&2
    exit 1
  fi
  rm -f "$run_lock_dir/pid"
  rmdir "$run_lock_dir" 2>/dev/null || true
  if ! mkdir "$run_lock_dir" 2>/dev/null; then
    echo "실행 잠금을 만들지 못했습니다: $run_lock_dir" >&2
    exit 1
  fi
fi
printf '%s\n' "$$" > "$run_lock_dir/pid"
cleanup_run_lock() {
  rm -f "$run_lock_dir/pid"
  rmdir "$run_lock_dir" 2>/dev/null || true
}
trap cleanup_run_lock 0

if [ "$mode" = restart ]; then
  for service in backend scheduler frontend; do
    if [ -z "$(docker compose ps -q "$service" 2>/dev/null)" ]; then
      echo "실행 중인 ${service} 컨테이너가 없습니다. 먼저 './run.sh'을 실행해 주세요." >&2
      exit 1
    fi
  done

  echo "백엔드를 재시작합니다…"
  docker compose restart backend
  attempt=0
  while ! curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 90 ]; then
      echo "백엔드 재시작을 확인하지 못했습니다. 'docker compose logs backend'를 확인해 주세요." >&2
      exit 1
    fi
    sleep 2
  done

  echo "스케줄러와 화면 서버를 재시작합니다…"
  docker compose restart scheduler frontend
  attempt=0
  while ! curl -fsS "$app_url" >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 60 ]; then
      echo "화면 서버 재시작을 확인하지 못했습니다. 'docker compose logs frontend'를 확인해 주세요." >&2
      exit 1
    fi
    sleep 2
  done

  echo ""
  echo "get-job 재시작 완료"
  echo "- 화면: $app_url"
  echo "- DB와 기존 데이터는 그대로 유지됩니다."
  exit 0
fi

legacy_volume=job-analyzer_postgres_data
configured_volume=$(read_env_value POSTGRES_VOLUME_NAME)
if ! safe_volume_name "$configured_volume"; then
  configured_volume=$legacy_volume
fi

if docker volume inspect "$configured_volume" >/dev/null 2>&1; then
  :
elif [ "$configured_volume" != "$legacy_volume" ] \
  && docker volume inspect "$legacy_volume" >/dev/null 2>&1; then
  configured_volume=$legacy_volume
  echo "기존 Job Analyzer DB 볼륨을 발견해 그대로 사용합니다."
else
  docker volume create "$configured_volume" >/dev/null
  echo "기존 DB 볼륨이 없어 새 로컬 DB 볼륨을 만들었습니다: $configured_volume"
fi
export POSTGRES_VOLUME_NAME=$configured_volume

postgres_user=$(read_env_value POSTGRES_USER)
postgres_database=$(read_env_value POSTGRES_DB)
if ! safe_database_name "$postgres_user"; then
  postgres_user=jobapp
fi
if ! safe_database_name "$postgres_database"; then
  postgres_database=jobdb
fi

echo "PostgreSQL을 준비합니다. 기존 공고·관심·숨김 데이터는 유지됩니다."
docker compose up -d db >/dev/null
attempt=0
while ! docker compose exec -T db pg_isready \
  -U "$postgres_user" -d "$postgres_database" >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 60 ]; then
    echo "PostgreSQL이 준비되지 않았습니다. 'docker compose logs db'를 확인해 주세요." >&2
    exit 1
  fi
  sleep 2
done

echo "get-job을 빌드하고 실행합니다…"
backend_container=""
backend_health=""
if existing_backend=$(docker compose ps -a -q backend 2>/dev/null); then
  backend_container=$existing_backend
fi
if [ -n "$backend_container" ]; then
  if existing_health=$(
    docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' \
      "$backend_container" 2>/dev/null
  ); then
    backend_health=$existing_health
  fi
fi
if [ "$backend_health" = "unhealthy" ]; then
  echo "응답하지 않는 기존 백엔드를 새 컨테이너로 복구합니다…"
  docker compose up --build --force-recreate --no-deps -d backend
fi
docker compose up --build -d

attempt=0
while ! curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 90 ]; then
    echo "백엔드 시작을 확인하지 못했습니다. 'docker compose logs backend'를 확인해 주세요." >&2
    exit 1
  fi
  sleep 2
done

attempt=0
while ! curl -fsS "$app_url" >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 60 ]; then
    echo "화면 서버 시작을 확인하지 못했습니다. 'docker compose logs frontend'를 확인해 주세요." >&2
    exit 1
  fi
  sleep 2
done

echo ""
echo "get-job 실행 완료"
echo "- 화면: $app_url"
echo "- 자동 수집: 매일 10:00, 13:00, 17:00 (Asia/Seoul)"
echo "- 수집 사이트: 리멤버, 데모데이, 그룹바이, 원티드, 점핏, 랠릿, 잡플래닛, Greenhouse, Lever, Ashby, Greeting, Ninehire"
echo "- DB 볼륨: $configured_volume"

open_app
