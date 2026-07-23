'use client'

import { Loader2, UserPlus } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { useCreateUser } from '@/lib/queries'

/** admin 直接创建用户对话框(内部产品化:无需邀请码)。 */
export function CreateUserDialog() {
  const create = useCreateUser()
  const [open, setOpen] = useState(false)
  const [username, setUsername] = useState('')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState('user')

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!username.trim() || !name.trim() || !password) return
    create.mutate(
      {
        username: username.trim(),
        name: name.trim(),
        email: email.trim() || undefined,
        password,
        role,
      },
      {
        onSuccess: () => {
          toast.success(`已创建用户 ${username.trim()}`)
          setUsername('')
          setName('')
          setEmail('')
          setPassword('')
          setRole('user')
          setOpen(false)
        },
        onError: (err) => {
          const msg = (err as { message?: string })?.message
          toast.error(msg || '创建失败')
        },
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <UserPlus className="size-4" />
          创建用户
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>创建用户</DialogTitle>
          <DialogDescription>
            直接创建账号,无需邀请码。创建后把密码线下告知对方。
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="cu-username">用户名</Label>
            <Input
              id="cu-username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              minLength={3}
              maxLength={32}
              pattern="^[a-zA-Z0-9_-]+$"
              placeholder="字母/数字/下划线/连字符,3-32 位"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="cu-name">姓名</Label>
            <Input
              id="cu-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              placeholder="对方姓名"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="cu-email">邮箱(可选)</Label>
            <Input
              id="cu-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="可选,用于联系方式"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="cu-password">初始密码</Label>
            <Input
              id="cu-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              placeholder="至少 8 位,创建后请告知对方"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="cu-role">角色</Label>
            <Select
              id="cu-role"
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="text-[13px]"
            >
              <option value="user">普通用户</option>
              <option value="admin">管理员</option>
            </Select>
          </div>
          <DialogFooter>
            <Button
              type="submit"
              disabled={create.isPending || !username.trim() || !name.trim() || !password}
            >
              {create.isPending ? (
                <>
                  <Loader2 className="size-3.5 animate-spin" />
                  创建中...
                </>
              ) : (
                '创建'
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
