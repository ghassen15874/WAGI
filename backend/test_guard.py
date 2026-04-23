from kilo.shared.write_guard import is_safe_generated_path
print(f"tailwind.config.js: {is_safe_generated_path('tailwind.config.js')}")
print(f"postcss.config.js: {is_safe_generated_path('postcss.config.js')}")
print(f"package.json: {is_safe_generated_path('package.json')}")
