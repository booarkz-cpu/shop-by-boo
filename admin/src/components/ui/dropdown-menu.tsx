import * as React from 'react';
import * as Primitive from '@radix-ui/react-dropdown-menu';
import {Check} from 'lucide-react';
import {cn} from '@/lib/utils';
const DropdownMenu=Primitive.Root,DropdownMenuTrigger=Primitive.Trigger,DropdownMenuRadioGroup=Primitive.RadioGroup,DropdownMenuLabel=Primitive.Label;
const DropdownMenuContent=React.forwardRef<React.ElementRef<typeof Primitive.Content>,React.ComponentPropsWithoutRef<typeof Primitive.Content>>(({className,sideOffset=8,...props},ref)=><Primitive.Portal><Primitive.Content ref={ref} sideOffset={sideOffset} collisionPadding={12} className={cn('ui-menu-content z-[1000] min-w-44 rounded-md border border-border bg-popover p-1 text-popover-foreground shadow-lg',className)} {...props}/></Primitive.Portal>);
DropdownMenuContent.displayName='DropdownMenuContent';
const DropdownMenuRadioItem=React.forwardRef<React.ElementRef<typeof Primitive.RadioItem>,React.ComponentPropsWithoutRef<typeof Primitive.RadioItem>>(({className,children,...props},ref)=><Primitive.RadioItem ref={ref} className={cn('ui-menu-item relative flex cursor-default select-none items-center gap-2 rounded-sm py-2 pr-8 pl-2 text-sm outline-none data-[highlighted]:bg-accent data-[disabled]:pointer-events-none data-[disabled]:opacity-50',className)} {...props}>{children}<span className="absolute right-2 flex size-4 items-center justify-center"><Primitive.ItemIndicator><Check className="size-4" aria-hidden="true"/></Primitive.ItemIndicator></span></Primitive.RadioItem>);
DropdownMenuRadioItem.displayName='DropdownMenuRadioItem';export {DropdownMenu,DropdownMenuTrigger,DropdownMenuContent,DropdownMenuRadioGroup,DropdownMenuRadioItem,DropdownMenuLabel};
