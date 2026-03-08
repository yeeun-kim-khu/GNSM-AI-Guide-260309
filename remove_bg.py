from PIL import Image
import os

# 파일 경로
input_path = os.path.join("assets", "ssadori_avatar.png")
output_path = os.path.join("assets", "ssadori_avatar_transparent.png")

print(f"이미지 로드 중: {input_path}")
img = Image.open(input_path)
img = img.convert("RGBA")

datas = img.getdata()
newData = []

# 흰색 배경을 투명하게 변환
for item in datas:
    # RGB 값이 모두 200 이상이면 흰색으로 간주하고 투명하게
    if item[0] > 200 and item[1] > 200 and item[2] > 200:
        newData.append((255, 255, 255, 0))  # 완전 투명
    else:
        newData.append(item)

img.putdata(newData)

print(f"배경 투명화 완료! 저장 중: {output_path}")
img.save(output_path, "PNG")

# 원본 파일 백업 후 교체
backup_path = os.path.join("assets", "ssadori_avatar_original.png")
if not os.path.exists(backup_path):
    os.rename(input_path, backup_path)
    print(f"원본 백업: {backup_path}")

os.rename(output_path, input_path)
print(f"✅ 완료! {input_path}가 투명 배경으로 교체되었습니다.")
