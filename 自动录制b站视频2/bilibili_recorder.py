
import subprocess
import os
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ================= 配置区域 =================
# 视频合集的第一个视频链接
START_URL = "https://www.bilibili.com/video/BV12bZ8YmE72/"
# 录像保存目录
OUTPUT_DIR = "recordings"
# ===========================================

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)


def sanitize_filename(name):
    """清理文件名中的非法字符"""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()


def start_ffmpeg_recording(filename):
    """启动 FFmpeg 录制进程"""
    output_path = os.path.join(OUTPUT_DIR, f"{filename}.mp4")
    print(f"🔴 开始录制: {output_path}")

    # ⚠️ 注意：如果你需要录制声音，需要修改下面的 command
    # 详见代码底部的【关于录制声音】说明
    command = [
        "ffmpeg",
        "-f", "gdigrab", "-framerate", "30", "-i", "desktop", # 视频源
        "-f", "dshow", "-i", "audio=麦克风阵列 (Realtek(R) Audio)", # 音频源
        "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac", # 音频编码
        "-y", output_path
    ]
    

    # 启动进程，静默输出以防刷屏
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,  # 如果需要调试 FFmpeg 报错，改为 subprocess.PIPE
        stderr=subprocess.DEVNULL
    )
    return process


def stop_ffmpeg_recording(process):
    """优雅停止录制"""
    if process:
        try:
            print("⏹️ 停止录制...")
            process.communicate(input=b'q', timeout=5)  # 发送 'q' 键停止
        except Exception:
            process.terminate()  # 强制结束
        print("✅ 录制文件已保存")


def get_video_status(driver):
    """通过 JS 获取播放器状态"""
    try:
        # 获取当前播放时间、总时长、是否结束、是否暂停
        status = driver.execute_script("""
            var v = document.querySelector('video');
            if (!v) return null;
            return {
                current: v.currentTime,
                duration: v.duration,
                ended: v.ended,
                paused: v.paused,
                src: v.src
            };
        """)
        return status
    except:
        return None


def main():
    # 1. 启动浏览器
    options = webdriver.ChromeOptions()
    # 屏蔽“Chrome正受到自动测试软件的控制”提示
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)

    driver = webdriver.Chrome(options=options)
    driver.get(START_URL)

    print("=" * 50)
    print("⚠️  请在浏览器中进行以下操作（限时 60 秒）：")
    print("1. 扫码登录 Bilibili（否则画质受限）")
    print("2. 确保【自动连播】开关已打开")
    print("3. 将画质切换到最高（1080P/4K）")
    print("4. 手动按 F11 或网页全屏，确保画面准备好")
    print("5. 准备好后，按回车键立即开始自动化流程...")
    print("=" * 50)

    # 等待用户手动确认，或者你可以用 time.sleep(60)
    input("👉 准备好后，请按回车键 (Enter) 开始脚本运行...")

    current_ffmpeg_process = None
    last_video_src = ""

    try:
        while True:  # 循环录制每一集
            # --- 等待视频加载 ---
            print("⏳ 等待视频元素加载...")
            video_element = WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.TAG_NAME, "video"))
            )

            # --- 获取当前视频标题 ---
            # B站标题通常在 h1 标签里
            time.sleep(2)  # 稍作等待确保标题刷新
            try:
                title_element = driver.find_element(By.TAG_NAME, "h1")
                video_title = sanitize_filename(title_element.get_attribute("title") or title_element.text)
            except:
                video_title = f"video_{int(time.time())}"

            print(f"🎬 检测到视频: {video_title}")

            # --- 确保视频开始播放 ---
            # 有时候 B 站会自动暂停，或者处于缓冲
            while True:
                status = get_video_status(driver)
                if status and status['current'] > 0 and not status['paused']:
                    # 检查是否是新视频（通过 src 或 URL 变化）
                    if status['src'] != last_video_src:
                        last_video_src = status['src']
                        break
                time.sleep(1)

            # --- 开始录制 ---
            current_ffmpeg_process = start_ffmpeg_recording(video_title)

            # --- 监控播放进度 ---
            print("👀 正在监控播放进度...")
            while True:
                status = get_video_status(driver)
                if not status:
                    break

                # 判定结束条件：
                # 1. HTML5 video 属性 ended 为 true
                # 2. 或者当前时间非常接近总时长 (误差 1 秒内)
                # 3. 或者 URL 发生了变化（B站切集会变 URL）

                is_near_end = (status['duration'] > 0) and (status['duration'] - status['current'] < 1.0)

                if status['ended'] or is_near_end:
                    print("🏁 本集播放结束")
                    break

                time.sleep(1)  # 每秒检查一次

            # --- 停止录制 ---
            stop_ffmpeg_recording(current_ffmpeg_process)
            current_ffmpeg_process = None

            # --- 等待跳转到下一集 ---
            print("🔄 等待自动连播跳转（15秒超时）...")

            # 记录当前 URL
            old_url = driver.current_url

            # 轮询检测 URL 是否变化
            url_changed = False
            for _ in range(15):  # 等待 15 秒
                time.sleep(1)
                if driver.current_url != old_url:
                    url_changed = True
                    print("✅ 检测到 URL 变化，准备录制下一集...")
                    # 稍微多等几秒，让 B 站的倒计时（3...2...1）结束，防止录到黑屏
                    time.sleep(3)
                    break

            if not url_changed:
                print("🛑 URL 未发生变化，判定为合集结束或自动连播失效。")
                break

    except KeyboardInterrupt:
        print("用户强制中断")
    except Exception as e:
        print(f"发生错误: {e}")
    finally:
        if current_ffmpeg_process:
            stop_ffmpeg_recording(current_ffmpeg_process)
        driver.quit()
        print("程序退出")


if __name__ == "__main__":
    main()
