#!/usr/bin/env python3
"""
🔄 Health Pipeline — мастер-скрипт полного цикла.
digest → fact_check → health_plan → shopping_list → Telegram @health_alex_bot
"""

import subprocess, sys, os
from pathlib import Path
from datetime import datetime

PROJECT = Path("/root/herm/health-bot")
SCRIPTS = {
    "digest": PROJECT / "digest.py",
    "fact_check": PROJECT / "fact_checker.py",
    "plan": PROJECT / "health_planner.py",
    "shopping": PROJECT / "shopping_list.py",
    "plan_html": PROJECT / "latest_plan.html",
}


def run_step(name: str, script: Path) -> bool:
    """Запустить один шаг пайплайна."""
    print(f"\n{'='*50}")
    print(f"⚙️  [{name.upper()}]")
    print(f"{'='*50}")
    
    try:
        result = subprocess.run(
            ["/usr/local/lib/hermes-agent/venv/bin/python3", str(script)],
            capture_output=True, text=True, timeout=600,
            cwd=str(PROJECT),
        )
        print(result.stdout[-2000:])  # Последние 2000 символов
        
        if result.returncode != 0:
            print(f"⚠️  [{name}] exit code {result.returncode}")
            if result.stderr:
                print(f"   stderr: {result.stderr[:500]}")
            return False
        
        return True
    except subprocess.TimeoutExpired:
        print(f"⏰ [{name}] TIMEOUT (>10 min)")
        return False
    except Exception as e:
        print(f"❌ [{name}] {e}")
        return False


def main():
    print(f"🏥 Health Pipeline — {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    
    results = {}
    
    # Шаг 1: Сбор видео + первичный AI-анализ
    results["digest"] = run_step("📥 Сбор видео", SCRIPTS["digest"])
    
    # Шаг 2: Фактчекинг
    results["fact_check"] = run_step("🔬 Фактчекинг", SCRIPTS["fact_check"])
    
    # Шаг 3: Health-план
    if results["fact_check"]:
        results["plan"] = run_step("📋 Health-план", SCRIPTS["plan"])
    else:
        print("\n⚠️  Пропускаем план (фактчекинг не прошёл)")
        results["plan"] = False
    
    # Шаг 4: Корзина покупок
    if results["plan"]:
        results["shopping"] = run_step("🛒 Корзина", SCRIPTS["shopping"])
    else:
        print("\n⚠️  Пропускаем корзину (план не сгенерирован)")
        results["shopping"] = False
    
    # Итог
    print(f"\n{'='*50}")
    print("📊 РЕЗУЛЬТАТЫ:")
    for step, ok in results.items():
        print(f"   {'✅' if ok else '❌'} {step}")
    
    # Вывод HTML-плана (cron доставит)
    if SCRIPTS["plan_html"].exists():
        html = SCRIPTS["plan_html"].read_text()
        print(f"\n{'='*50}")
        print(html)
    
    print(f"\n🏁 Pipeline завершён — {datetime.now().strftime('%H:%M')}")


if __name__ == "__main__":
    main()
