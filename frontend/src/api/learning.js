import axios from 'axios'

// X-Audit-Reason carries UTF-8 percent encoding, never raw Unicode.
export function auditHeaders (reason) {
  if (reason === undefined || reason === null || reason === '') return {}
  if (typeof reason !== 'string' || Array.from(reason).length > 1000 || /[\x00-\x1f\x7f-\x9f]/.test(reason)) {
    throw new Error('审计理由最长 1000 个字符且不能含控制字符')
  }
  const encoded = encodeURIComponent(reason)
  if (encoded.length > 4096) throw new Error('审计理由编码后最长 4096 字节')
  return {'X-Audit-Reason': encoded}
}

function teacherRead (url, classId, reason) {
  return axios.get(url, {
    baseURL: '/api',
    params: {class_id: classId},
    headers: auditHeaders(reason)
  })
}

export function getTeacherStudentProfile (studentId, classId, reason) {
  return teacherRead(`admin/learning/student/${encodeURIComponent(studentId)}/profile`, classId, reason)
}

export function getClassKnowledgeStats (classId, reason) {
  return teacherRead('admin/learning/class/knowledge-stats', classId, reason)
}
