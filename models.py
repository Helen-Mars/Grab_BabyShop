import re
from pydantic import BaseModel, Field, field_validator
from typing import Optional


class Config(BaseModel):
    """配置模型，用于验证和管理应用配置"""
    
    email: str = Field(
        description="登录邮箱"
    )
    
    product_url: str = Field(
        description="目标商品链接"
    )
    
    target_quantity: int = Field(
        ge=1,
        description="目标购买数量，至少为1"
    )
    
    color_selection_enabled: bool = Field(
        description="是否启用颜色选择功能"
    )
    
    target_color: Optional[str] = Field(
        description="目标颜色正则表达式"
    )
    
    card_number: str = Field(
        description="信用卡卡号"
    )
    
    card_expiry: str = Field(
        description="信用卡有效期 (格式: MM/YY)"
    )
    
    card_cvv: str = Field(
        description="信用卡 CVV"
    )
    
    cardholder_name: str = Field(
        description="持卡人姓名"
    )
    
    resident_id: str = Field(
        description="身份证号"
    )
    
    auto_pay: bool = Field(
        description="是否自动支付（慎用）"
    )
    
    check_interval: float = Field(
        ge=0.1,
        description="检查商品状态的间隔（秒），至少为0.1秒"
    )

    @field_validator('email')
    @classmethod
    def validate_email(cls, v: str) -> str:
        value = (v or "").strip()
        if not value:
            raise ValueError("登录邮箱不能为空")
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("邮箱格式不正确")
        return value

    @field_validator('product_url')
    @classmethod
    def validate_product_url(cls, v: str) -> str:
        value = (v or "").strip()
        if not value:
            raise ValueError("商品链接不能为空")
        if not value.startswith("https://store.babyssb.co.jp/"):
            raise ValueError("商品链接必须是 https://store.babyssb.co.jp/ 下的地址")
        if "/products/" not in value:
            raise ValueError("商品链接必须指向具体商品页面")
        product_code = value.split("/products/", 1)[1].strip().strip("/")
        if not product_code:
            raise ValueError("商品链接缺少产品编码")
        return value

    @field_validator('target_color')
    @classmethod
    def validate_target_color(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        value = v.strip()
        return value or None

    @field_validator('card_number')
    @classmethod
    def validate_card_number(cls, v: str) -> str:
        value = (v or "").strip()
        if not value:
            return ""
        digits = re.sub(r"\D", "", value)
        if not re.fullmatch(r"\d{13,19}", digits):
            raise ValueError("信用卡卡号必须是 13 到 19 位数字")
        return digits
    
    @field_validator('card_expiry')
    @classmethod
    def validate_card_expiry(cls, v: str) -> str:
        """验证信用卡有效期格式"""
        value = (v or "").strip()
        if not value:
            return ""
        digits = re.sub(r"\D", "", value)
        if len(digits) != 4:
            raise ValueError("信用卡有效期格式应为 MM/YY")
        month = int(digits[:2])
        year = digits[2:]
        if month < 1 or month > 12:
            raise ValueError("信用卡有效期月份必须在 01 到 12 之间")
        return f"{digits[:2]}/{year}"

    @field_validator('card_cvv')
    @classmethod
    def validate_card_cvv(cls, v: str) -> str:
        value = (v or "").strip()
        if not value:
            return ""
        digits = re.sub(r"\D", "", value)
        if not re.fullmatch(r"\d{3,4}", digits):
            raise ValueError("信用卡 CVV 必须是 3 或 4 位数字")
        return digits

    @field_validator('cardholder_name')
    @classmethod
    def validate_cardholder_name(cls, v: str) -> str:
        value = (v or "").strip()
        if not value:
            return ""
        if len(value) < 2 or len(value) > 64:
            raise ValueError("持卡人姓名长度必须在 2 到 64 个字符之间")
        if not re.fullmatch(r"[A-Za-z][A-Za-z\s.'-]*", value):
            raise ValueError("持卡人姓名应使用银行卡上的英文姓名")
        return value

    @field_validator('resident_id')
    @classmethod
    def validate_resident_id(cls, v: str) -> str:
        value = (v or "").strip().upper()
        if not value:
            return ""
        if not re.fullmatch(r"[A-Z0-9-]{6,20}", value):
            raise ValueError("Resident ID 只能包含大写字母、数字和连字符，长度 6 到 20 位")
        return value
    
    @field_validator('check_interval')
    @classmethod
    def validate_check_interval(cls, v: float) -> float:
        """确保检查间隔合理"""
        if v < 0.1:
            raise ValueError("检查间隔不能小于0.1秒")
        if v > 60:
            raise ValueError("检查间隔不能大于60秒")
        return v
    
    @field_validator('target_quantity')
    @classmethod
    def validate_target_quantity(cls, v: int) -> int:
        """确保购买数量至少为1"""
        if v < 1:
            raise ValueError("购买数量至少为1")
        if v > 20:
            raise ValueError("购买数量不能超过20")
        return v
