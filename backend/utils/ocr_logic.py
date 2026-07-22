def extract_text_from_image(results):
    print("📄 Hasil EasyOCR:")
    for r in results:
        print("-", r)

    if not results or len(results) < 3:
        print("❌ OCR hasil terlalu sedikit:", results)
        return {}

    no_sertifikat = ""
    name = ""
    student_id = ""
    department = ""
    test_date = ""

    combined = list(map(str.strip, results))
    for i, line in enumerate(combined):
        line_lower = line.lower()

        if "no:" in line_lower and not no_sertifikat:
            if ":" in line:
                parts = line.split(":")
                if len(parts) > 1 and len(parts[1].strip()) > 5:
                    no_sertifikat = parts[1].strip()
            elif i + 1 < len(combined):
                next_line = combined[i + 1].strip()
                if len(next_line) > 5:
                    no_sertifikat = next_line

        elif "name" in line_lower and not name:
            if i + 1 < len(combined):
                possible_name = combined[i + 1].strip()
                if len(possible_name.split()) >= 2:
                    name = possible_name

        elif "student id" in line_lower and not student_id:
            if i + 1 < len(combined):
                sid = combined[i + 1].strip()
                if sid.isdigit() and len(sid) >= 6:
                    student_id = sid
            elif line.strip().isdigit() and len(line.strip()) >= 6:
                student_id = line.strip()

        elif "department" in line_lower and not department:
            if i + 1 < len(combined):
                department = combined[i + 1].strip()

        elif "test date" in line_lower and not test_date:
            if i + 1 < len(combined):
                test_date_line = combined[i + 1].strip()
                if test_date_line.startswith(":"):
                    test_date_line = test_date_line[1:].strip()
                test_date = test_date_line

    print("📌 Ekstrak OCR:", f"{no_sertifikat}|{name}|{student_id}|{department}|{test_date}")

    if all([no_sertifikat, name, student_id]):
        return {
            "no_sertifikat": no_sertifikat,
            "name": name,
            "student_id": student_id,
            "department": department,
            "test_date": test_date
        }
    return {}